"""Service for anchoring AI chunks to PDF coordinates."""
from text_utils import normalize_text, normalize_text_for_matching
from coordinate_utils import (
    calculate_chunk_box,
    calculate_encompassing_box,
    pdf_lines_for_match,
    calculate_match_score,
    lines_are_continuous,
    is_page_break_continuation
)
from table_processor import find_best_matching_table, find_matching_tables_cross_page
from config import Config


def anchor_chunks_to_pdf(result_chunks, structured):
    """
    Anchor AI result chunks back to PDF coordinates by matching text content.
    """
    
    # Build searchable list of text lines from structured data
    pdf_lines = pdf_lines_for_match(structured)
    used_line_ids = set()  # Track used lines
    used_table_ids = set()  # Track used tables so each is matched at most once

    # Build a flat list of ALL tables across every page
    all_tables = [el for el in structured if el.get("type") == "table"]

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
        if chunk_type == "image":
            # Images already have box coordinates from extraction, just ensure anchored flag is set
            if chunk.get("metadata", {}).get("box"):
                chunk["metadata"]["anchored"] = True
                print(f"[PDF Parse] Image chunk already anchored: page={chunk_page}, "
                      f"box={chunk['metadata']['box']}")
            else:
                chunk["metadata"]["anchored"] = False
                print(f"[WARN] Image chunk missing box coordinates")
                
        elif chunk_type == "table":
            print(f"[PDF Parse] Processing table chunk on page {chunk_page}")
            matched_tables = find_matching_tables_cross_page(
                chunk_text, all_tables,
                preferred_page=chunk_page,
                excluded_ids=used_table_ids,
            )

            if not matched_tables:
                # Fallback: AI may have split one table into row-chunks.
                # Retry without excluding already-used tables so every
                # row-chunk still anchors to the same table element.
                matched_tables = find_matching_tables_cross_page(
                    chunk_text, all_tables,
                    preferred_page=chunk_page,
                    excluded_ids=None,
                )
                if matched_tables:
                    print(f"[PDF Parse] Table matched via used-table fallback")

            if matched_tables:
                for mt in matched_tables:
                    mt_id = mt.get("id", "")
                    if mt_id:
                        used_table_ids.add(mt_id)

                table_box = calculate_encompassing_box(matched_tables)

                if isinstance(table_box, list):
                    chunk["metadata"]["boxes"] = table_box
                    chunk["metadata"]["page"] = table_box[0].get("page", chunk_page)
                else:
                    chunk["metadata"]["box"] = table_box
                    chunk["metadata"]["page"] = matched_tables[0].get("page", chunk_page)

                chunk["metadata"]["table_id"] = matched_tables[0].get("id", "")
                chunk["metadata"]["anchored"] = True
                pages = [t.get("page", "?") for t in matched_tables]
                print(f"[PDF Parse] Anchored table: pages={pages}, "
                      f"id={chunk['metadata']['table_id']}")
            else:
                chunk["metadata"]["anchored"] = False
                print(f"[WARN] No matching table found for chunk (preferred page {chunk_page})")

        else:
            # Split chunk text into individual lines
            chunk_lines = [line.strip() for line in chunk_text.split('\n') if line.strip()]

            # Find matching lines in structured output
            matched_lines = []
            matched_line_ids = []

            # `start_idx` was previously advanced after every successful match
            # (`start_idx = matched_idx + len(matched_line_list)`). That made
            # anchoring DOCUMENT-ORDER DEPENDENT — perfectly valid for a
            # strictly sequential AI output, but the merge step interleaves
            # image chunks back into the array and `is_design_heavy` paths
            # can emit chunks slightly out of order. The advance caused later
            # chunks that referenced earlier-page content to silently fail
            # to anchor (and thus refuse to highlight on click). We now
            # always restart the search from line 0 and rely entirely on
            # `used_line_ids` to prevent double-matching. The cost is a
            # bigger inner loop, but the fast `if line_id in used_line_ids:
            # continue` skip keeps it cheap, and correctness wins.
            for chunk_line in chunk_lines:
                match_result = match_chunk_to_lines_with_exclusion(
                    chunk_line, pdf_lines, 0, used_line_ids
                )
                if match_result:
                    matched_idx, matched_line_list = match_result
                    matched_lines.extend(matched_line_list)

                    # Extract IDs and mark as used
                    for line in matched_line_list:
                        line_id = line.get("id", "")
                        if line_id:
                            matched_line_ids.append(line_id)
                            used_line_ids.add(line_id)

                    print(f"[PDF Parse] Matched chunk line '{chunk_line[:30]}...' to {len(matched_line_list)} PDF lines")
                else:
                    print(f"[WARN] Could not match chunk line: '{chunk_line[:50]}...'")

            # Calculate encompassing bounding box from matched lines
            if matched_lines:
                chunk_box = calculate_chunk_box(matched_lines)
                
                # Handle both single box and multiple boxes (cross-page)
                if isinstance(chunk_box, list):
                    # Multiple boxes (cross-page content)
                    chunk["metadata"]["boxes"] = chunk_box
                    chunk["metadata"]["page"] = chunk_box[0].get("page", matched_lines[0].get("page", 1))
                    chunk["metadata"]["line_count"] = len(matched_lines)
                    chunk["metadata"]["anchored"] = True
                    chunk["metadata"]["matched_line_ids"] = matched_line_ids
                    
                    print(f"[PDF Parse] Anchored cross-page chunk: pages={[b['page'] for b in chunk_box]}, "
                          f"lines={len(matched_lines)}, boxes={len(chunk_box)}")
                else:
                    # Single box (same-page content)
                    chunk["metadata"]["box"] = chunk_box
                    chunk["metadata"]["page"] = matched_lines[0].get("page", 1)
                    chunk["metadata"]["line_count"] = len(matched_lines)
                    chunk["metadata"]["anchored"] = True
                    chunk["metadata"]["matched_line_ids"] = matched_line_ids
                    
                    print(f"[PDF Parse] Anchored text chunk: page={chunk['metadata']['page']}, "
                          f"lines={len(matched_lines)}, box={chunk_box}")
            else:
                # Mark as unanchored but still add metadata structure
                chunk["metadata"]["anchored"] = False
                chunk["metadata"]["matched_line_ids"] = []
                print(f"[WARN] No lines matched for chunk: '{chunk_text[:50]}...'")
    
    return result_chunks


def match_chunk_to_lines_with_exclusion(chunk_text, pdf_lines, start_idx=0, used_line_ids=None):
    """
    Enhanced matching that finds the BEST multi-line match, including cross-page spans.
    Uses fuzzy matching to handle punctuation differences.
    """
    if used_line_ids is None:
        used_line_ids = set()
        
    normalized_chunk = normalize_text(chunk_text)
    fuzzy_chunk = normalize_text_for_matching(chunk_text)
    
    # 1. Try single line matches first (exact and fuzzy)
    for i in range(start_idx, len(pdf_lines)):
        line = pdf_lines[i]
        line_id = line.get("id", "")
        
        if line_id in used_line_ids:
            continue
            
        line_text = line.get("text", "")
        normalized_line = normalize_text(line_text)
        fuzzy_line = normalize_text_for_matching(line_text)
        
        # EXACT match
        if normalized_chunk == normalized_line:
            return (i, [line])
        
        # FUZZY match (handles punctuation differences)
        if fuzzy_chunk == fuzzy_line:
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
        
        for j in range(i + 1, min(i + Config.CROSS_PAGE_LINE_WINDOW, len(pdf_lines))):
            next_line = pdf_lines[j]
            next_line_id = next_line.get("id", "")
            
            if next_line_id in used_line_ids:
                break
                
            # Enhanced proximity check for cross-page spans
            if not lines_are_continuous(combined_lines[-1], next_line):
                # Don't break immediately - check if it's a page break continuation
                if not is_page_break_continuation(combined_lines[-1], next_line):
                    break
            
            # Add line to combination
            combined_lines.append(next_line)
            combined_text_parts.append(next_line.get("text", ""))
            
            # Test combined text
            combined_text = " ".join(combined_text_parts)
            normalized_combined = normalize_text(combined_text)
            fuzzy_combined = normalize_text_for_matching(combined_text)
            
            # Calculate match quality using both exact and fuzzy matching
            exact_score = calculate_match_score(normalized_chunk, normalized_combined)
            fuzzy_score = calculate_match_score(fuzzy_chunk, fuzzy_combined)
            
            # Use the higher score (fuzzy matching is more lenient)
            match_score = max(exact_score, fuzzy_score)
            
            # Update best match if this is better
            if match_score > best_score:
                best_match = (i, combined_lines.copy())
                best_score = match_score
                
                # If we have a perfect match, we can return immediately
                if match_score >= 100:  # Perfect match
                    return best_match
    
    # Return the best match found, if any
    if best_match and best_score >= Config.MATCH_SCORE_THRESHOLD:
        return best_match
    
    return None
