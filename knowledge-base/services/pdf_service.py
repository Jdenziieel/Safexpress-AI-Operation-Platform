"""PDF processing service - orchestrates the entire PDF processing pipeline."""
import io
import uuid
import pdfplumber
from datetime import datetime
from core.pdf_extractor import assemble_elements, build_simplified_view_from_elements
from services.chunking_service import (
    process_text_only, 
    process_images_only, 
    merge_text_and_image_chunks,
    is_design_heavy_simple
)
from services.anchoring_service import anchor_chunks_to_pdf
from utils.file_utils import save_json


def parse_and_chunk_pdf_file(file_bytes, source_filename):
    """
    Combined function: Parse PDF file, extract structure, and create semantic chunks.
    
    Args:
        file_bytes: PDF file content as bytes
        source_filename: Name of the source PDF file
        
    Returns:
        dict: Final result with chunks and metadata
    """
    print(f"[DEBUG] Processing uploaded file: {source_filename}")

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
    save_json(structured, "structured_output_v3.json")

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
        # Design-heavy processing would go here
        # For now, fall back to standard processing
        pass

    # Standard two-pass processing
    print("[DEBUG] Using STANDARD two-pass processing")
    
    # Generate a single pipeline_id for this entire document processing session
    pipeline_id = f"doc-{uuid.uuid4().hex[:12]}"
    print(f"[DEBUG] Pipeline ID: {pipeline_id}")
    
    text_result = process_text_only(simplified_view, filename=source_filename, pipeline_id=pipeline_id)
    image_result = process_images_only(images, simplified_view, filename=source_filename, pipeline_id=pipeline_id)
    
    # Merge chunks
    merged_result = merge_text_and_image_chunks(
        text_result, 
        image_result, 
        simplified_view, 
        structured,
        source_filename
    )
    
    # Save merged result
    save_json(merged_result, "two_pass_final_result.json")
    print("[DEBUG] two_pass_final_result.json created successfully")

    # Anchor chunks to PDF coordinates
    anchored_chunks = anchor_chunks_to_pdf(
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
    
    # Save Anchored result
    save_json(anchored_chunks, "final_anchored_result.json")
    print("[DEBUG] final_anchored_result.json created successfully")
    
    return final_result
