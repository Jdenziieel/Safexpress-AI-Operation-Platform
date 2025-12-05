import io
import json
import os
import re
import statistics
from datetime import datetime
import pdfplumber
from flask import Flask, request, jsonify
from flask_cors import CORS
from pprint import pprint
from dotenv import load_dotenv
import fitz
import base64
from openai import OpenAI
import uuid  # Add this import at the top
import weaviate
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType, ReferenceProperty
import glob

load_dotenv()

# --- Flask setup ---
app = Flask(__name__)
CORS(app)

# --- OpenAI setup (commented) ---
load_dotenv(override=True)  # make sure dotenv is loaded
openai_api_key = os.environ.get("OPENAI_APIKEY")
openai_api_base = os.environ.get("OPENAI_API_BASE")

if not openai_api_key:
    print("⚠️ Could not find OPENAI_APIKEY  in environment. Falling back to dotenv...")
    from dotenv import dotenv_values
    env_vars = dotenv_values(".env")
    openai_api_key = env_vars.get("OPENAI_APIKEY")

if not openai_api_key:
    raise RuntimeError("❌ OPENAI_API_KEY environment variable is not set!")

client = OpenAI(api_key=openai_api_key)
headers = {
    "X-OpenAI-Api-Key": openai_api_key,
    # "X-OpenAI-Api-Base": openai_api_base,
}
weaviate_url = os.environ.get("WEAVIATE_URL")
weaviate_api_key = os.environ.get("WEAVIATE_API_KEY")

weaviate_client = weaviate.connect_to_weaviate_cloud(
    cluster_url=weaviate_url,
    auth_credentials=weaviate.auth.AuthApiKey(weaviate_api_key),
    headers=headers
)

def insert_document(file_metadata: dict, chunks: list, doc_id: str = None):
    """Insert a parent Document and all its KnowledgeBase chunks."""
    
    # Ensure collections exist
    if "Document" not in weaviate_client.collections.list_all():
        weaviate_client.collections.create(
            name="Document",
            properties=[
                Property(name="file_name", data_type=DataType.TEXT),
                Property(name="page_count", data_type=DataType.NUMBER),
            ]
        )

    if "KnowledgeBase" not in weaviate_client.collections.list_all():
        weaviate_client.collections.create(
            name="KnowledgeBase",
            vector_config=[
                Configure.Vectors.text2vec_openai(
                    name="text_vector",
                    source_properties=["text"],
                    model="text-embedding-3-small",
                    dimensions=1536
                )
            ],
            generative_config=Configure.Generative.openai(
                model="gpt-4o",
                temperature=0.0,
            ),
            properties=[
                Property(name="text", data_type=DataType.TEXT),
                Property(name="type", data_type=DataType.TEXT),
                Property(name="section", data_type=DataType.TEXT),
                Property(name="context", data_type=DataType.TEXT),
                Property(name="tags", data_type=DataType.TEXT_ARRAY),
                Property(name="page", data_type=DataType.NUMBER),
                Property(name="chunk_id", data_type=DataType.TEXT),
                Property(name="created_at", data_type=DataType.TEXT),
            ],
            references=[
                ReferenceProperty(name="ofDocument", target_collection="Document"),
            ]
        )

    # Generate or reuse Document ID
    doc_id = doc_id or str(uuid.uuid4())

    # Insert parent Document
    weaviate_client.collections.get("Document").data.insert(file_metadata, uuid=doc_id)

    # Insert child chunks
    chunks_collection = weaviate_client.collections.get("KnowledgeBase")
    with chunks_collection.batch.fixed_size(batch_size=100) as batch:
        for c in chunks:
            meta = c.get("metadata", {})
            chunk_obj = {
                "text": c.get("text"),
                "type": meta.get("type", "text"),
                "section": meta.get("section", ""),
                "context": meta.get("context", ""),
                "tags": meta.get("tags", []),
                "created_at": meta.get("created_at", ""),
                "ofDocument": {"beacon": f"weaviate://localhost/Document/{doc_id}"},
                "page": meta.get("page", None),
                "chunk_id": c.get("chunk_id", None),
            }
            batch.add_object(chunk_obj)

    print(f"✅ Inserted Document {file_metadata['file_name']} with {len(chunks)} chunks")
    return doc_id

def delete_document_and_chunks(doc_id: str):
    """Delete a document and cascade delete all its chunks."""
    docs = weaviate_client.collections.get("Document")
    chunks = weaviate_client.collections.get("KnowledgeBase")

    # Delete children (chunks)
    chunks.data.delete_many(
        where={
            "path": ["ofDocument", "id"],
            "operator": "Equal",
            "valueText": doc_id
        }
    )

    # Delete parent (document)
    docs.data.delete_by_id(doc_id)

    print(f"🗑️ Deleted Document {doc_id} and all related chunks")


def replace_document(file_metadata: dict, chunks: list, doc_id: str):
    """Replace an existing Document and its chunks with new content."""
    # Delete old doc + chunks
    delete_document_and_chunks(doc_id)

    # Reinsert with the same doc_id (to keep references stable)
    new_doc_id = insert_document(file_metadata, chunks, doc_id=doc_id)

    print(f"♻️ Replaced Document {file_metadata['file_name']} with {len(chunks)} chunks")
    return new_doc_id

def query_weaviate():
    knowledge_base = weaviate_client.collections.use("KnowledgeBase")

    generate_prompt = """You are an assistant for a logistics company’s knowledge base. You are given chunks of text retrieved from company documents (policies, manuals, contracts, and other uploaded files). Your task is to:

    Answer the user’s question based only on the provided chunks.

    Summarize or explain clearly if the answer requires synthesis across multiple chunks.

    Always cite your sources by including the document name, section, and page number (if available) where the information came from.

    If the answer is not found in the chunks, say that the information is not available in the provided documents. Do not make up information."""

    query_text = "Who are the members of the project?"

    # Retrieve chunks using hybrid search
    response = knowledge_base.query.hybrid(
        query=query_text,
        alpha=0.5,  # set to 1 for pure vector, or e.g. 0.75 for hybrid
        limit=20,
    )

    #print number of chunks retrieved
    print(f"Initial retrieval: {len(response.objects)} chunks")

    # Step 2: Rerank the retrieved chunks
    reranked_chunks = rerank_with_openai(query_text, response.objects, top_m=10)
    print(f"After reranking: {len(reranked_chunks)} chunks")

    # Step 3: Extract just the chunk objects for context
    top_chunks = [chunk for chunk, score in reranked_chunks]
    
    # Build context string from top reranked chunks
    context_parts = []
    for i, (chunk, score) in enumerate(reranked_chunks, 1):
        props = chunk.properties
        source_info = f"[Source: {props.get('section', 'Unknown')}, Page {props.get('page', 'N/A')}]"
        context_parts.append(f"Chunk {i} (relevance: {score:.2f}): {props.get('text', '')} {source_info}")
    
    context_text = "\n\n".join(context_parts)
    
    # Generate final response using OpenAI directly
    messages = [
        {"role": "system", "content": generate_prompt},
        {"role": "user", "content": f"Query: {query_text}\n\nContext:\n{context_text}\n\nAnswer:"}
    ]
    
    try:
        generation_response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.0,
            max_tokens=1000
        )
        
        generated_answer = generation_response.choices[0].message.content
        
        # Print results
        print("Retrieved and reranked context:")
        for i, (chunk, score) in enumerate(reranked_chunks, 1):
            print(f"\nChunk {i} (Score: {score:.2f}):")
            print(json.dumps(chunk.properties, indent=2))
        
        print(f"\nGenerated Answer:\n{generated_answer}")
        
        return {
            "answer": generated_answer,
            "context_chunks": [chunk.properties for chunk, score in reranked_chunks],
            "rerank_scores": [score for chunk, score in reranked_chunks]
        }
        
    except Exception as e:
        print(f"Error in generation: {e}")
        return None
    
def rerank_with_openai(query, retrieved_chunks, top_m=5):
    # Ask the model to score relevance
    reranked = []
    for chunk in retrieved_chunks:
        text = chunk.properties.get("text", "")
        if not text.strip():
            continue
            
        prompt = f"""Score the relevance of this passage to the query on a scale of 0.0 to 1.0.
        Only respond with a number.

        Query: {query}
        Passage: {text[:1000]}...

        Relevance score:"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=10
            )
            
            score_text = response.choices[0].message.content.strip()
            # Extract just the number from the response
            import re
            score_match = re.search(r'(\d*\.?\d+)', score_text)
            if score_match:
                score = float(score_match.group(1))
                score = min(1.0, max(0.0, score))  # Clamp between 0 and 1
            else:
                score = 0.0
                
            reranked.append((chunk, score))
            
        except Exception as e:
            print(f"Error scoring chunk: {e}")
            # Fallback score
            reranked.append((chunk, 0.5))
    
    # Sort by score, descending
    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked[:top_m]

# --- STEP 1: Extract text, tables, figures/images, fonts ---
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
            
            # Debug problematic gaps
            # if gap > line_word_tol:
            #     print(f"[DEBUG [PROBLIMATIC]]")
            #     print(f"[DEBUG] Word break: '{prev.get('text', '')}'->'{ch.get('text', '')}' gap={gap:.2f} tol={line_word_tol:.2f}")
            
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
            # print(f"Word: '{text}' | Length: {len(w)} | Chars: {[c.get('text', '') for c in w]}")
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
                # try to find words in table rows to estimate bbox (best-effort)
                # fallback to whole page if can't compute
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
            "id": unique_table_id,  # ✅ Add unique ID
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

# --- Extract images using PyMuPDF ---
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

# --- STEP 3: Endpoint ---
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

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _anchor_chunks_to_pdf(result_chunks, structured):
    """
    Anchor AI result chunks back to PDF coordinates by matching text content.
    """
    
    # Build searchable list of text lines from structured data
    pdf_lines = _pdf_lines_for_match(structured)
    used_line_ids = set()  # ✅ Track used linesf
   
    # Create lookup for tables and images by page
    tables_by_page = {}
    
    for element in structured:
        page = element.get("page", 1)
        if element.get("type") == "table":
            if page not in tables_by_page:
                tables_by_page[page] = []
            tables_by_page[page].append(element)

    for chunk_idx, chunk in enumerate(result_chunks):
        chunk_text = chunk.get("text", "")
        chunk_type = chunk.get("metadata", {}).get("type", "")
        chunk_page = chunk.get("metadata", {}).get("page", 1)

        if not chunk_text.strip():
            continue
        
        # Initialize metadata if not present --- safety check ---
        if "metadata" not in chunk:
            chunk["metadata"] = {}
                    
        # Handle different content types
        if chunk_type == "table":
            print(f"[DEBUG] Processing table chunk on page {chunk_page}")
            # Find matching table in structured data by page
            if chunk_page in tables_by_page:
                # Take the first available table on that page (you could improve matching logic)
                best_table = find_best_matching_table(chunk_text, tables_by_page[chunk_page])
                
                if best_table:
                    # Copy the box coordinates directly from structured data
                    chunk["metadata"]["box"] = best_table.get("box", {})
                    chunk["metadata"]["page"] = best_table.get("page", chunk_page)
                    chunk["metadata"]["table_id"] = best_table.get("id", "")  # ✅ Add table ID
                    chunk["metadata"]["anchored"] = True
                    print(f"[DEBUG] Anchored table: page={chunk['metadata']['page']}, "
                          f"box={chunk['metadata']['box']}, id={chunk['metadata']['table_id']}")
                else:
                    chunk["metadata"]["anchored"] = False
                    print(f"[WARN] No matching table found on page {chunk_page} for chunk content")
            else:
                chunk["metadata"]["anchored"] = False
                print(f"[WARN] No table found on page {chunk_page}")

        else:
            # ✅ PRESERVE ALL YOUR EXISTING LINE-BY-LINE LOGIC
            # Split chunk text into individual lines
            chunk_lines = [line.strip() for line in chunk_text.split('\n') if line.strip()]  
            
            # Find matching lines in structured output
            matched_lines = []
            matched_line_ids = []
            start_idx = 0
            
            for chunk_line in chunk_lines:
                match_result = _match_chunk_to_lines_with_exclusion(
                    chunk_line, pdf_lines, start_idx, used_line_ids
                )
                if match_result:
                    matched_idx, matched_line_list = match_result
                    matched_lines.extend(matched_line_list)
                    
                    # Extract IDs and mark as used
                    for line in matched_line_list:
                        line_id = line.get("id", "")
                        if line_id:
                            matched_line_ids.append(line_id)
                            used_line_ids.add(line_id)  # ✅ Mark as used
                    
                    start_idx = matched_idx + len(matched_line_list)
                    print(f"[DEBUG] Matched chunk line '{chunk_line[:30]}...' to {len(matched_line_list)} PDF lines")
                else:
                    print(f"[WARN] Could not match chunk line: '{chunk_line[:50]}...'")

            # Calculate encompassing bounding box from matched lines
            if matched_lines:
                chunk_box = _calculate_chunk_box(matched_lines)
                
                # Add box and page info to chunk metadata
                chunk["metadata"]["box"] = chunk_box
                chunk["metadata"]["page"] = matched_lines[0].get("page", 1)
                chunk["metadata"]["line_count"] = len(matched_lines)
                chunk["metadata"]["anchored"] = True  # Flag to indicate successful anchoring
                chunk["metadata"]["matched_line_ids"] = matched_line_ids  # ✅ Add line IDs
                
                print(f"[DEBUG] Anchored text chunk: page={chunk['metadata']['page']}, "
                      f"lines={len(matched_lines)}, box={chunk_box}")
            else:
                # Mark as unanchored but still add metadata structure
                chunk["metadata"]["anchored"] = False
                chunk["metadata"]["matched_line_ids"] = []  # ✅ Empty array for unanchored
                print(f"[WARN] No lines matched for chunk: '{chunk_text[:50]}...'")
    
    return result_chunks  # Return the modified chunks

def _match_chunk_to_lines_with_exclusion(chunk_text, pdf_lines, start_idx=0, used_line_ids=None):
    """
    Enhanced matching that finds the BEST multi-line match, including cross-page spans.
    """
    if used_line_ids is None:
        used_line_ids = set()
        
    normalized_chunk = _normalize(chunk_text)
    
    # 1. Try single line matches first (exact only)
    for i in range(start_idx, len(pdf_lines)):
        line = pdf_lines[i]
        line_id = line.get("id", "")
        
        if line_id in used_line_ids:
            continue
            
        line_text = line.get("text", "")
        normalized_line = _normalize(line_text)
        
        # EXACT match only
        if normalized_chunk == normalized_line:
            return (i, [line])
    
    # 2. Multi-line matching with cross-page support
    best_match = None
    best_score = 0
    
    for i in range(start_idx, len(pdf_lines) - 1):
        line = pdf_lines[i]
        line_id = line.get("id", "")
        
        if line_id in used_line_ids:
            continue
            
        # Try combining with subsequent lines (increased search window for cross-page)
        combined_lines = [line]
        combined_text_parts = [line.get("text", "")]
        
        for j in range(i + 1, min(i + 20, len(pdf_lines))):  # ✅ Increased from 12 to 20
            next_line = pdf_lines[j]
            next_line_id = next_line.get("id", "")
            
            if next_line_id in used_line_ids:
                break
                
            # ✅ Enhanced proximity check for cross-page spans
            if not _lines_are_continuous(combined_lines[-1], next_line):
                # Don't break immediately - check if it's a page break continuation
                if not _is_page_break_continuation(combined_lines[-1], next_line):
                    break
            
            # Add line to combination
            combined_lines.append(next_line)
            combined_text_parts.append(next_line.get("text", ""))
            
            # Test combined text
            combined_text = " ".join(combined_text_parts)
            normalized_combined = _normalize(combined_text)
            
            # Calculate match quality
            match_score = _calculate_match_score(normalized_chunk, normalized_combined)
            
            # Update best match if this is better
            if match_score > best_score:
                best_match = (i, combined_lines.copy())
                best_score = match_score
                
                # If we have a perfect match, we can return immediately
                if match_score >= 100:  # Perfect match
                    return best_match
    
    # Return the best match found, if any
    if best_match and best_score >= 80:  # Minimum 80% match required
        return best_match
    
    return None

def _is_page_break_continuation(line1, line2):
    """
    Check if line2 is a continuation of line1 across a page break.
    This handles cases where text flows from the bottom of one page to the top of the next.
    """
    try:
        page1 = line1.get("page", 1)
        page2 = line2.get("page", 1)
        
        # Must be consecutive pages
        if page2 != page1 + 1:
            return False
        
        # Line1 should be near the bottom of its page
        line1_box = line1.get("box", {})
        page1_height = line1.get("page_height", 792)  # Default PDF height
        line1_bottom = line1_box.get("b", 0)
        
        # Line2 should be near the top of its page
        line2_box = line2.get("box", {})
        line2_top = line2_box.get("t", 0)
        
        # ✅ More lenient thresholds for your document
        bottom_threshold = page1_height * 0.6  # Last 40% of page (was 80%)
        is_line1_near_bottom = line1_bottom > bottom_threshold
        
        top_threshold = page1_height * 0.4     # First 40% of page (was 20%)
        is_line2_near_top = line2_top < top_threshold
        
        # Check horizontal alignment (similar indentation)
        line1_indent = line1.get("indent", line1_box.get("l", 0))
        line2_indent = line2.get("indent", line2_box.get("l", 0))
        indent_diff = abs(line1_indent - line2_indent)
        
        # ✅ More lenient indent variation (50 pixels instead of 20)
        similar_indent = indent_diff < 50
        
        return is_line1_near_bottom and is_line2_near_top and similar_indent
        
    except (KeyError, TypeError, AttributeError):
        return False

def _lines_are_continuous(line1, line2):
    """
    Enhanced version that checks both same-page proximity and cross-page continuation.
    """
    # Same page check
    if _lines_are_on_same_page(line1, line2):
        return _lines_are_vertically_close(line1, line2, threshold_multiplier=2.0)
    
    # Cross-page check
    return _is_page_break_continuation(line1, line2)

def _calculate_chunk_box(matched_lines):
    """
    Enhanced version that handles cross-page bounding boxes correctly.
    """
    if not matched_lines:
        return {"l": 0, "t": 0, "r": 0, "b": 0}
    
    # Flatten the matched_lines list in case it contains nested lists
    flattened_lines = []
    for item in matched_lines:
        if isinstance(item, list):
            flattened_lines.extend(item)
        else:
            flattened_lines.append(item)

    # Get all line boxes
    line_boxes = []
    for line in flattened_lines:
        if isinstance(line, dict) and "box" in line and line["box"]:
            line_boxes.append(line["box"])
    
    if not line_boxes:
        return {"l": 0, "t": 0, "r": 0, "b": 0}
    
    # ✅ Group boxes by page for cross-page handling
    boxes_by_page = {}
    for i, line in enumerate(flattened_lines):
        page = line.get("page", 1)
        boxes_by_page.setdefault(page, []).append((line_boxes[i], line))
    
    # ✅ Calculate bounds considering page structure
    if len(boxes_by_page) == 1:
        # Single page - use existing logic
        line_boxes.sort(key=lambda box: box.get("t", 0))
        top = line_boxes[0].get("t", 0)
        bottom = line_boxes[-1].get("b", 0)
        left = min(box.get("l", 0) for box in line_boxes)
        right = max(box.get("r", 0) for box in line_boxes)
    else:
        # Cross-page - use first line's top and last line's bottom
        first_page = min(boxes_by_page.keys())
        last_page = max(boxes_by_page.keys())
        
        # Top from first page's first line
        first_page_boxes = sorted(boxes_by_page[first_page], key=lambda x: x[0].get("t", 0))
        top = first_page_boxes[0][0].get("t", 0)
        
        # Bottom from last page's last line  
        last_page_boxes = sorted(boxes_by_page[last_page], key=lambda x: x[0].get("t", 0))
        bottom = last_page_boxes[-1][0].get("b", 0)
        
        # Left and right from all boxes
        all_boxes = [box for box, _ in sum(boxes_by_page.values(), [])]
        left = min(box.get("l", 0) for box in all_boxes)
        right = max(box.get("r", 0) for box in all_boxes)
    
    return {
        "l": left,
        "t": top, 
        "r": right,
        "b": bottom
    }

def _calculate_match_score(chunk_text, combined_text):
    """
    Calculate match score between chunk and combined text.
    Returns score from 0-100.
    """
    if not chunk_text or not combined_text:
        return 0
    
    # Exact match = 100%
    if chunk_text == combined_text:
        return 100
    
    # Containment matches
    if chunk_text in combined_text:
        # Score based on how much of combined text is the chunk
        return int((len(chunk_text) / len(combined_text)) * 95)
    
    if combined_text in chunk_text:
        # Score based on how much of chunk is covered
        return int((len(combined_text) / len(chunk_text)) * 90)
    
    # Word-based similarity for partial matches
    chunk_words = set(chunk_text.split())
    combined_words = set(combined_text.split())
    
    if not chunk_words:
        return 0
    
    intersection = chunk_words & combined_words
    union = chunk_words | combined_words
    
    # Jaccard similarity * 85 (max score for word-based match)
    similarity = len(intersection) / len(union) if union else 0
    return int(similarity * 85)

def _lines_are_on_same_page(line1, line2):
    """Check if two lines are on the same page"""
    return line1.get("page") == line2.get("page")

def _lines_are_vertically_close(line1, line2, threshold_multiplier=2.0):
    """
    Check if two lines are vertically close enough to be considered continuous.
    Uses a more generous threshold for multi-line matching.
    """
    try:
        line1_box = line1.get("box", {})
        line2_box = line2.get("box", {})
        
        line1_bottom = line1_box.get("b", 0)
        line2_top = line2_box.get("t", 0)
        
        # Calculate line heights
        line1_height = line1_box.get("b", 0) - line1_box.get("t", 0)
        line2_height = line2_box.get("b", 0) - line2_box.get("t", 0)
        avg_height = (line1_height + line2_height) / 2
        
        # Gap between lines
        gap = line2_top - line1_bottom
        
        # Lines are close if gap is less than 2x average line height (more generous)
        return gap < (avg_height * threshold_multiplier) if avg_height > 0 else False
    except (KeyError, TypeError, ZeroDivisionError):
        return False
    
def _pdf_lines_for_match(structured):
    """
    Extract text lines from structured output, preserving line objects with metadata.
    """
    lines = []
    for element in structured:
        if element.get("type") == "text" and "text" in element:
            lines.append({
                "text": element["text"],
                "box": element.get("box", {}),
                "page": element.get("page", 1),
                "id": element.get("id", ""),
                "type": element.get("type", "text")
            })
        # Save the anchored result
        # with open("_pdf_lines_for_match_V1.json", "w") as f:
        #     json.dump(lines, f, indent=2)   
    return lines

def find_best_matching_table(chunk_text, page_tables):
    """
    Find the best matching table on a page by comparing chunk text with table content
    """
    if not page_tables or not chunk_text.strip():
        return None
    
    best_table = None
    best_score = 0
    
    print(f"[DEBUG] Matching table chunk against {len(page_tables)} tables on page")
    
    for table_idx, table in enumerate(page_tables):
        table_content = extract_table_text_content(table)
        
        if not table_content:
            print(f"[DEBUG] Table {table_idx} has no extractable content")
            continue
            
        # Calculate similarity between chunk text and table content
        similarity_score = calculate_table_similarity(chunk_text, table_content)
        
        print(f"[DEBUG] Table {table_idx} similarity: {similarity_score:.2f}")
        print(f"[DEBUG] Table content preview: {table_content[:100]}...")
        
        if similarity_score > best_score:
            best_score = similarity_score
            best_table = table
            
    # Require minimum similarity threshold
    if best_score >= 0.3:  # 30% similarity threshold
        print(f"[DEBUG] ✅ Selected table with {best_score:.2f} similarity")
        return best_table
    else:
        print(f"[DEBUG] ❌ No table met similarity threshold (best: {best_score:.2f})")
        return None

def extract_table_text_content(table):
    """
    Extract all text content from a table structure for comparison
    """
    table_data = table.get("table", [])
    if not table_data:
        return ""
    
    # Flatten all table cells into a single text string
    all_text_parts = []
    for row in table_data:
        if isinstance(row, (list, tuple)):
            for cell in row:
                if cell and str(cell).strip():
                    all_text_parts.append(str(cell).strip())
        elif row and str(row).strip():
            all_text_parts.append(str(row).strip())
    
    return " | ".join(all_text_parts)

def calculate_table_similarity(chunk_text, table_content):
    """
    Calculate similarity between AI chunk text and extracted table content
    """
    if not chunk_text or not table_content:
        return 0.0
    
    # Normalize both texts
    chunk_normalized = _normalize(chunk_text.lower())
    table_normalized = _normalize(table_content.lower())
    
    # Method 1: Check if table content is contained in chunk (AI descriptions often include table data)
    if table_normalized in chunk_normalized:
        containment_score = len(table_normalized) / len(chunk_normalized)
        return min(0.95, containment_score * 1.2)  # Boost containment matches
    
    # Method 2: Check if chunk is contained in table content  
    if chunk_normalized in table_normalized:
        containment_score = len(chunk_normalized) / len(table_normalized)
        return min(0.90, containment_score * 1.1)
    
    # Method 3: Word overlap similarity
    chunk_words = set(chunk_normalized.split())
    table_words = set(table_normalized.split())
    
    if not chunk_words or not table_words:
        return 0.0
    
    intersection = chunk_words & table_words
    union = chunk_words | table_words
    
    jaccard_similarity = len(intersection) / len(union) if union else 0.0
    
    # Method 4: Key table terms bonus (look for table-specific keywords in chunk)
    table_indicators = {'table', 'program', 'defense', 'date', 'title', 'members', 'adviser'}
    chunk_words_lower = set(word.lower() for word in chunk_text.split())
    
    if table_indicators & chunk_words_lower:
        jaccard_similarity *= 1.3  # 30% bonus for table-related terms
    
    return min(1.0, jaccard_similarity)

JSON_SCHEMA = """{
  "chunks": [
    {
      "text": "string",
      "metadata": {
        "type": "heading|paragraph|list|table|image",
        "section": "string",
        "context": "string (maximum one sentence)",
        "tags": ["string"],
        "row_index": "integer (for tables only) or null",
        "continues": "boolean",
        "is_page_break": "boolean",
        "siblings": ["string"],  
        "page": "integer"
      }
    }
  ]
}"""

def process_text_only(simplified_view):
    """
    First pass: Process text content only for structural analysis
    """
    # Remove image markers from simplified_view for clean text processing
    image_pat = re.compile(r"\[IMAGE\s+page=(\d+)\s+l=([\d.]+)\s+t=([\d.]+)\s+r=([\d.]+)\s+b=([\d.]+)\]")
    clean_text = image_pat.sub("[IMAGE_PLACEHOLDER]", simplified_view)
    
    # Text-only prompt focused on structure and content
    text_prompt = f"""You are a PDF text analyzer that outputs structured JSON.
                        Your task is to:
                        1. Analyze the text content and identify its logical structure.
                        2. Split it into **meaningful text chunks** - paragraphs, headings, lists, tables.
                        3. Ignore [IMAGE_PLACEHOLDER] markers - they will be processed separately.

                        **Chunking Guidelines:**
                        - Focus on textual content organization
                        - Group related text elements (headers with descriptions, list items together)
                        - Identify document sections and hierarchies
                        - Keep table text structure intact
                        - Create fewer, more meaningful chunks rather than line-by-line splits

                        **Output Schema:**
                        {JSON_SCHEMA}

                        **Text Processing Rules:**
                        - Strip formatting markers (*bold*, _italic_, <s=XX>) from output
                        - Preserve original line breaks and spacing
                        - Mark chunks that are likely headers, paragraphs, lists, or tables
                        - Use context to describe the role of each text chunk
                        """

    messages = [
        {"role": "system", "content": text_prompt},
        {"role": "user", "content": clean_text[:20000]}  # Limit text size
    ]
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0
        )
        
        text_result = json.loads(response.choices[0].message.content)
        
        # Save text-only result
        with open("text_only_chunks.json", "w") as f:
            json.dump(text_result, f, indent=2)
        
        print(f"[DEBUG] Text-only processing: {len(text_result.get('chunks', []))} chunks created")
        return text_result
        
    except Exception as e:
        print(f"[ERROR] Text-only processing failed: {e}")
        return {"chunks": []}

def process_images_only(images, simplified_view):
    """
    Second pass: Process images separately with rich context
    """
    if not images:
        return {"chunks": []}
    
    image_chunks = []
    image_pat = re.compile(r"\[IMAGE\s+page=(\d+)\s+l=([\d.]+)\s+t=([\d.]+)\s+r=([\d.]+)\s+b=([\d.]+)\]")
    
    # ✅ FIXED: Store context for each individual marker
    image_contexts = []  # Use list instead of dict
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
    with open("image_context.json", "w") as f:
        json.dump(image_contexts, f, indent=2)

    print(f"[DEBUG] Found {len(image_contexts)} image markers in simplified view")
    print(f"[DEBUG] Found {len(images)} images with base64 data")

    # ✅ Helper function to match image to context by coordinates
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

    # ✅ Create lookup dictionary for images by ID for precise box retrieval
    images_by_id = {image.get("id", f"img-{idx}"): image for idx, image in enumerate(images)}
    print(f"[DEBUG] Created image lookup with {len(images_by_id)} entries")

    # Process each image with its matching context
    for idx, image in enumerate(images):
        page = image.get("page", 1)
        image_id = image.get("id", f"img-{idx}")  # ✅ Get image ID
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
            # Process single image
            response = client.chat.completions.create(
                model="gpt-4o",
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
                temperature=0.0
            )
            
            description = response.choices[0].message.content
            
            # ✅ Get precise bounding box from original image data
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
                    "image_id": image_id,  # ✅ Include original image ID
                    "box": precise_box,    # ✅ Precise coordinates from original data
                    "anchored": True if precise_box else False
                }
            }
            
            image_chunks.append(image_chunk)
            print(f"[DEBUG] ✅ Processed image {idx+1} from page {page}")
            
        except Exception as e:
            print(f"[ERROR] Failed to process image {idx+1}: {e}")
            continue
    
    result = {"chunks": image_chunks}
    
    # Save image-only result
    with open("image_only_chunks.json", "w") as f:
        json.dump(result, f, indent=2)
    
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
        estimated_position = (i / len(text_chunks)) * total_text_length
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

# def detect_image_regions(image_b64):
#     """Detect non-text regions that likely contain images/graphics"""
    
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

# # # def get_layout_analysis(image_b64):
# # #     """Use AI to identify text vs image regions with approximate coordinates"""
    
# # #     layout_prompt = """Analyze this image and identify distinct regions:

# # # 1. Text regions: Areas containing readable text
# # # 2. Image regions: Photos, graphics, logos, charts
# # # 3. Provide approximate bounding box coordinates as percentages (0-100)

# # # Format your response as JSON:
# # # {
# # #   "regions": [
# # #     {
# # #       "type": "text|image|logo|graphic",
# # #       "description": "brief description",
# # #       "bbox": {"left": 10, "top": 20, "right": 90, "bottom": 50}
# # #     }
# # #   ]
# # # }"""

# # #     try:
# # #         response = client.chat.completions.create(
# # #             model="gpt-4o",
# # #             messages=[
# # #                 {"role": "system", "content": layout_prompt},
# # #                 {
# # #                     "role": "user",
# # #                     "content": [
# # #                         {"type": "text", "text": "Identify all regions in this image:"},
# # #                         {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
# # #                     ]
# # #                 }
# # #             ],
# # #             response_format={"type": "json_object"},
# # #             temperature=0.1
# # #         )
        
# # #         layout_data = json.loads(response.choices[0].message.content)
# # #         return layout_data.get("regions", [])
        
# # #     except Exception as e:
# # #         print(f"[ERROR] Layout analysis failed: {e}")
# # #         return []

# # # def extract_text_with_ocr(image_b64):
# # #     """
# # #     Extract text with bounding boxes using OCR
# # #     """
# # #     try:
# # #         # Decode base64 image
# # #         image_data = base64.b64decode(image_b64)
# # #         image = Image.open(io.BytesIO(image_data))
        
# # #         # Convert to numpy array for OpenCV
# # #         img_array = np.array(image)
        
# # #         # Use pytesseract to get detailed info
# # #         ocr_data = pytesseract.image_to_data(img_array, output_type=pytesseract.Output.DICT)
        
# # #         # Group words into text blocks
# # #         text_blocks = []
# # #         current_block = []
# # #         current_line = None
        
# # #         for i in range(len(ocr_data['text'])):
# # #             confidence = int(ocr_data['conf'][i])
# # #             text = ocr_data['text'][i].strip()
            
# # #             # Skip low confidence and empty text
# # #             if confidence < 30 or not text:
# # #                 continue
                
# # #             word_info = {
# # #                 'text': text,
# # #                 'left': ocr_data['left'][i],
# # #                 'top': ocr_data['top'][i], 
# # #                 'width': ocr_data['width'][i],
# # #                 'height': ocr_data['height'][i],
# # #                 'line_num': ocr_data['line_num'][i],    
# # #                 'block_num': ocr_data['block_num'][i],
# # #                 'confidence': confidence
# # #             }
            
# # #             # Group by block and line numbers
# # #             if (current_line is None or 
# # #                 ocr_data['line_num'][i] != current_line or 
# # #                 ocr_data['block_num'][i] != current_block):
                
# # #                 # Save previous block if it exists
# # #                 if current_block:
# # #                     text_blocks.append(current_block)
                
# # #                 # Start new block
# # #                 current_block = [word_info]
# # #                 current_line = ocr_data['line_num'][i]
# # #             else:
# # #                 current_block.append(word_info)
        
# # #         # Don't forget the last block
# # #         if current_block:
# # #             text_blocks.append(current_block)
        
# # #         # Convert to text chunks with bounding boxes
# # #         text_chunks = []
# # #         for block_idx, block in enumerate(text_blocks):
# # #             if not block:
# # #                 continue
                
# # #             # Combine all words in the block
# # #             text_parts = [word['text'] for word in block]
# # #             combined_text = ' '.join(text_parts)
            
# # #             if not combined_text.strip():
# # #                 continue
                
# # #             # Calculate block bounding box
# # #             left = min(word['left'] for word in block)
# # #             top = min(word['top'] for word in block) 
# # #             right = max(word['left'] + word['width'] for word in block)
# # #             bottom = max(word['top'] + word['height'] for word in block)
            
# # #             # Normalize coordinates (0-1 range)
# # #             img_width, img_height = image.size
            
# # #             # Calculate confidence score (average of all words in block)
# # #             avg_confidence = sum(word['confidence'] for word in block) / len(block)
            
# # #             text_chunks.append({
# # #                 'text': combined_text,
# # #                 'box': {
# # #                     'l': left / img_width,
# # #                     't': top / img_height,
# # #                     'r': right / img_width,
# # #                     'b': bottom / img_height
# # #                 },
# # #                 'type': 'text',
# # #                 'confidence': avg_confidence,
# # #                 'word_count': len(block),
# # #                 'block_id': f"ocr-block-{block_idx}"
# # #             })
        
# # #         print(f"[DEBUG] OCR extracted {len(text_chunks)} text blocks from image")
# # #         return text_chunks
        
# # #     except Exception as e:
# # #         print(f"[ERROR] OCR processing failed: {e}")
# # #         import traceback
# # #         traceback.print_exc()
# # #         return []
        
# # def process_design_heavy_pdf_simplified(images, source_filename):
# #     """Simplified design-heavy processing using OCR + Computer Vision only"""
    
# #     all_chunks = []
# #     all_text_regions = []  # ✅ Collect all text regions
# #     all_image_regions = []  # ✅ Collect all image regions
    
# #     for idx, image in enumerate(images):
# #         page = image.get("page", 1)
# #         image_b64 = image['image_b64']
        
# #         print(f"[DEBUG] Processing design-heavy image from page {page}")
        
# #         # Step 1: OCR to extract text regions with bounding boxes
# #         try:
# #             text_regions = extract_text_with_ocr(image_b64)
# #             print(f"[DEBUG] Found {len(text_regions)} text regions via OCR")

# #              # ✅ Add page info and collect text regions
# #             for region in text_regions:
# #                 region['source_page'] = page
# #                 region['source_filename'] = source_filename
# #             all_text_regions.extend(text_regions)

# #         except Exception as e:
# #             print(f"[WARN] OCR failed: {e}")
# #             text_regions = []
        
# #         # Step 2: Computer Vision to detect image regions  
# #         try:
# #             image_regions = detect_image_regions(image_b64)
# #             print(f"[DEBUG] Found {len(image_regions)} image regions via CV")

# #             # ✅ Add page info and collect image regions
# #             for region in image_regions:
# #                 region['source_page'] = page
# #                 region['source_filename'] = source_filename
# #             all_image_regions.extend(image_regions)
            
# #         except Exception as e:
# #             print(f"[WARN] Image detection failed: {e}")
# #             image_regions = []
        
# #         # Step 3: Add ONE comprehensive analysis of the full image
# #         # (This replaces multiple region analyses)
# #         try:
# #             ai_result = analyze_image_with_region_validation(
# #                 image_b64, page, text_regions, image_regions, source_filename
# #             )
            
# #             # Step 4: Map AI chunks to precise bounding boxes
# #             page_chunks = map_ai_chunks_to_detected_regions(
# #                 ai_result, text_regions, image_regions, page, source_filename
# #             )
            
# #             all_chunks.extend(page_chunks)
# #             print(f"[DEBUG] Created {len(page_chunks)} validated chunks from page {page}")
            
# #         except Exception as e:
# #             print(f"[WARN] Full image analysis failed: {e}")

# #         # ✅ Save extracted regions to separate files (simple approach)
# #         try:
# #             # Save text regions
# #             with open("extracted_text_regions.json", "w") as f:
# #                 json.dump(all_text_regions, f, indent=2)
# #             print(f"[DEBUG] Saved {len(all_text_regions)} text regions to extracted_text_regions.json")
            
# #             # Save image regions
# #             with open("extracted_image_regions.json", "w") as f:
# #                 json.dump(all_image_regions, f, indent=2)
# #             print(f"[DEBUG] Saved {len(all_image_regions)} image regions to extracted_image_regions.json")
            
# #             # Save processed chunks
# #             with open("processed_chunks.json", "w") as f:
# #                 json.dump(all_chunks, f, indent=2)
# #             print(f"[DEBUG] Saved {len(all_chunks)} processed chunks to processed_chunks.json")

# #         except Exception as save_error:
# #             print(f"[ERROR] Failed to save extracted data: {save_error}")
            
# #     return {
# #         "chunks": all_chunks,
# #         "processing_info": {
# #             "method": "design_heavy_ocr_only",
# #             "total_chunks": len(all_chunks),
# #             "processed_at": datetime.now().isoformat()
# #         }
# #     }


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

# Keep the existing calculate_encompassing_bbox function as is
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
        
#     except json.JSONDecodeError as e:
#         print(f"[ERROR] Failed to parse JSON response: {e}")
#         return []
#     except Exception as e:
#         print(f"[ERROR] Analysis failed: {e}")
#         return []

@app.route('/parse-pdf', methods=['POST'])
def parse_and_chunk_pdf():
    """Combined endpoint: Upload PDF file, extract structure, and create semantic chunks"""
    print("[DEBUG] Starting combined parse-and-chunk-pdf function")
    
    # Check if file was uploaded
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "File is not a PDF"}), 400

    source_filename = file.filename
    print(f"[DEBUG] Processing uploaded file: {source_filename}")

    try:
        file_bytes = file.read()
        structured = []

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                page_elems = assemble_elements(file_bytes, page, i)

                for el in page_elems:
                    el["page"] = i + 1
                    el["page_width"] = page.width
                    el["page_height"] = page.height
                structured.extend(page_elems)

        simplified_view = build_simplified_view_from_elements(structured)
        print(f"[DEBUG] Extracted structure: {len(structured)} elements")
        print(f"[DEBUG] Simplified view length: {len(simplified_view)}")
        
        # Save structured output for debugging
        with open("structured_output_v3.json", "w") as f:
            json.dump(structured, f, indent=2)

        # STEP 2: Design-heavy detection
        is_design_heavy, confidence, reasons = is_design_heavy_simple(structured)
        print(f"[DEBUG] Detection result: {is_design_heavy} (confidence: {confidence:.1%})")
        for reason in reasons:
            print(f"[DEBUG] - {reason}")

        # STEP 3: Collect images with base64 data
        images = []
        for el in structured:
            if el.get("type") == "image" and el.get("image_b64"):
                images.append({
                    "image_b64": el["image_b64"],
                    "id": el.get("id", ""),
                    "box": el.get("box", {}),
                    "page": el.get("page", 1)
                })
        print(f"[DEBUG] Found {len(images)} images with base64 data")

        # STEP 4: Process based on document type
        if is_design_heavy:
            print("[DEBUG] Using DESIGN-HEAVY processing")
            # result = process_design_heavy_pdf_simplified(images, source_filename)    
            # return jsonify(result), 200

        else:
            print("[DEBUG] Using STANDARD two-pass processing")  
            # Two-pass processing
            text_result = process_text_only(simplified_view)
            image_result = process_images_only(images, simplified_view)
            
            # Merge chunks
            merged_result = merge_text_and_image_chunks(
                text_result, 
                image_result, 
                simplified_view, 
                structured,
                source_filename
            )
            
            # Save merged result
            with open("two_pass_final_result.json", "w") as f:
                json.dump(merged_result, f, indent=2)
            print("[DEBUG] two_pass_final_result.json created successfully")

            # Anchor chunks to PDF coordinates
            anchored_chunks = _anchor_chunks_to_pdf(
                merged_result.get("chunks", []), 
                structured
            )
            
            # Create final result with all metadata
            final_result = {
                "chunks": anchored_chunks,
                "document_metadata": {
                    "source_file": source_filename,
                    "processed_date": datetime.now().isoformat(),
                    "total_chunks": len(anchored_chunks),
                    "processing_version": "combined_v1.0",
                    "processing_method": "standard_two_pass",
                    "anchored_chunks": sum(1 for chunk in anchored_chunks if chunk.get("metadata", {}).get("anchored", False)),
                    "unanchored_chunks": sum(1 for chunk in anchored_chunks if not chunk.get("metadata", {}).get("anchored", False)),
                    "design_heavy_detection": {
                        "is_design_heavy": is_design_heavy,
                        "confidence": confidence,
                        "reasons": reasons
                    }
                },
                "processing_info": merged_result.get("processing_info", {}),
                "extraction_summary": {
                    "total_elements": len(structured),
                    "text_elements": len([el for el in structured if el.get("type") == "text"]),
                    "table_elements": len([el for el in structured if el.get("type") == "table"]), 
                    "image_elements": len(images),
                    "simplified_view_chars": len(simplified_view)
                }
            }
            # Save Anchored  result
            with open("final_anchored_result.json", "w") as f:
                json.dump(anchored_chunks, f, indent=2)
            print("[DEBUG] final_anchored_result.json created successfully")

            
            return jsonify(final_result), 200

    except Exception as e:
        print(f"\n[ERROR] Combined processing failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500
    
@app.route('/upload-to-kb', methods=['POST'])
def upload_to_kb():
    """Endpoint to upload processed chunks to knowledge base"""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    data = request.get_json()
    chunks = data.get('chunks', [])
    document_metadata = data.get('document_metadata', {})
    source_filename = data.get('source_filename', 'unknown.pdf')
    
    if not chunks:
        return jsonify({"error": "No chunks provided"}), 400
    
    try:
        # Prepare file metadata for the Document collection
        file_metadata = {
            "file_name": source_filename,
            "page_count": document_metadata.get('total_pages', 0) or max(
                (chunk.get('metadata', {}).get('page', 0) for chunk in chunks), 
                default=0
            )
        }
        
        # Add chunk_id to each chunk if not present
        for i, chunk in enumerate(chunks):
            if not chunk.get('id') and not chunk.get('chunk_id'):
                chunk['chunk_id'] = chunk.get('id', f"chunk-{i}-{str(uuid.uuid4())[:8]}")
            elif chunk.get('id') and not chunk.get('chunk_id'):
                chunk['chunk_id'] = chunk['id']
        
        # Use your insert_document function to save to Weaviate
        doc_id = insert_document(file_metadata, chunks)
        
        # Also save to file for backup/debugging
        kb_filename = f"kb_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{source_filename.replace('.pdf', '')}.json"
        kb_entry = {
            "document_metadata": document_metadata,
            "source_filename": source_filename,
            "upload_timestamp": datetime.now().isoformat(),
            "doc_id": doc_id,
            "chunks": chunks
        }
        
        with open(kb_filename, "w") as f:
            json.dump(kb_entry, f, indent=2)
        
        print(f"[INFO] Successfully uploaded {len(chunks)} chunks to knowledge base with doc_id: {doc_id}")
        
        return jsonify({
            "success": True, 
            "message": f"Successfully uploaded {len(chunks)} chunks to knowledge base",
            "doc_id": doc_id,
            "filename": kb_filename
        }), 200
        
    except Exception as e:
        print(f"[ERROR] Failed to upload to knowledge base: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False, 
            "error": f"Internal server error: {str(e)}"
        }), 500


@app.route('/list-kb', methods=['GET'])
def list_kb_files():
    """Endpoint to list all knowledge base files"""
    try:
        # Find all files matching the kb_*.json pattern
        kb_files = glob.glob("kb_*.json")
        # Sort by creation time (newest first)
        kb_files.sort(key=os.path.getmtime, reverse=True)
        
        # Create a list of file info
        file_list = []
        for filepath in kb_files:
            filename = os.path.basename(filepath)
            # Extract timestamp and original filename from the kb_filename
            # Example: kb_20240615_143022_sample.pdf.json
            parts = filename.replace('kb_', '').rsplit('_', 2)
            if len(parts) >= 3:
                date_str = parts[0]
                time_str = parts[1]
                orig_filename = '_'.join(parts[2:]).replace('.json', '')
                upload_time = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
            else:
                upload_time = "Unknown"
                orig_filename = filename.replace('kb_', '').replace('.json', '')

            file_list.append({
                "filename": filename,
                "original_filename": orig_filename,
                "upload_time": upload_time,
                "size": os.path.getsize(filepath)
            })

        return jsonify({
            "success": True,
            "files": file_list
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Internal server error: {str(e)}"
        }), 500

if __name__ == '__main__':
    app.run(debug=True, port=8009)
